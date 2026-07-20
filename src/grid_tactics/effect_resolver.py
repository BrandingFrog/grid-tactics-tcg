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
from grid_tactics.cards import CardDefinition, EffectDefinition, is_dark_mage
from grid_tactics.engine_events import (
    EVT_CARD_BURNED,
    EVT_CARD_DRAWN,
    EVT_DARK_MATTER_CHANGE,
    EVT_MINION_HP_CHANGE,
    EVT_MINION_MOVED,
    EVT_MINION_TRANSFORMED,
    EVT_PENDING_MODAL_OPENED,
    EVT_PENDING_MODAL_RESOLVED,
    EVT_PLAYER_HP_CHANGE,
    EventStream,
)
from grid_tactics.enums import EffectType, Element, PlayerSide, TargetType, TriggerType
from grid_tactics.game_state import GameState, PendingDeathTarget
from grid_tactics.minion import MinionInstance
from grid_tactics.phase_contracts import assert_phase_contract
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


def _validate_target_at_resolve_time(
    state: GameState,
    effect: EffectDefinition,
    source_pos: Optional[tuple[int, int]],
    source_minion_id: Optional[int],
    target_pos: Optional[tuple[int, int]],
) -> bool:
    """Phase 14.7-06: Return True if the effect can still resolve (no fizzle).

    Per spec §7.3, an effect fizzles SILENTLY when its target is no longer
    valid at resolution time. This helper is the source of truth for
    fizzle eligibility and is called from ``resolve_effect`` before the
    TargetType dispatch.

    Fizzle rules by TargetType:
      - SINGLE_TARGET: fizzle if no alive minion exists at target_pos.
        (A missing minion OR a dead-but-not-yet-cleaned-up minion both
        fizzle — the effect captured a target that no longer exists.)
      - ADJACENT: when source_minion_id is supplied, fizzle if that
        minion is dead / missing. Adjacency is computed from the source
        minion's current position; a dead source cannot project an aura.
        Magic-card / aura callers (source_minion_id=None) rely on
        source_pos and never fizzle here — area logic naturally no-ops
        on empty neighbor sets.
      - SELF_OWNER: when source_minion_id is supplied (the caster is a
        minion), fizzle if the minion is dead / missing. Magic-card
        casts with source_minion_id=None always pass — SELF_OWNER then
        refers to the casting player, which is always valid.
      - OPPONENT_PLAYER: never fizzles (the player is always "alive"
        for targeting purposes until game over, which exits earlier).
      - Area effects (ALL_ENEMIES, ALL_ALLIES, ALL_MINIONS): never
        fizzle via this helper — their handlers recompute the target
        list from state and silently no-op on empty sets.

    Returns True if the effect can proceed to resolution, False if it
    must fizzle (caller returns state unchanged).
    """
    tt = effect.target

    if tt == TargetType.SINGLE_TARGET:
        if target_pos is None:
            # No target captured — the handler already no-ops on this.
            # Return True so existing callers see the same identity
            # (unchanged state) through the normal path, not a fizzle
            # short-circuit. Either way produces a silent no-op.
            return True
        m = _find_minion_at_pos(state.minions, target_pos)
        if m is None or m.current_health <= 0:
            return False
        return True

    if tt == TargetType.ADJACENT:
        if source_minion_id is not None:
            src = state.get_minion(source_minion_id)
            if src is None or src.current_health <= 0:
                return False
        return True

    if tt == TargetType.SELF_OWNER:
        if source_minion_id is not None:
            src = state.get_minion(source_minion_id)
            if src is None or src.current_health <= 0:
                return False
        return True

    # OPPONENT_PLAYER / ALL_ENEMIES / ALL_ALLIES / ALL_MINIONS — never
    # fizzle via this helper.
    return True


def _player_index_for_side(side: PlayerSide) -> int:
    """Return the player tuple index for a PlayerSide."""
    return int(side)


def _effect_tribe_matches(card_def: CardDefinition, target_tribe: str) -> bool:
    """Tribe filter for area effects (ALL_ALLIES / ALL_MINIONS).

    Dark Matter pool redesign 2026-07: the special filter value
    "Dark Mage" routes through the single ``is_dark_mage`` predicate
    (Mage tribe AND element DARK; composite tribes count since
    2026-07-10 — Ratchanter "Mage Rat" and Grave Caller "Mage Undead"
    are Dark Mages). Any other value keeps the legacy case-insensitive
    substring semantics.
    """
    normalized = target_tribe.strip().lower()
    if normalized in ("dark mage", "dark_mage"):
        return is_dark_mage(card_def)
    return bool(card_def.tribe) and normalized in card_def.tribe.lower()


def _count_friendly_dark_mages(
    state: GameState, side: PlayerSide, library: CardLibrary,
) -> int:
    """Count the LIVE friendly minions satisfying ``is_dark_mage``."""
    count = 0
    for m in state.minions:
        if m.owner != side or m.current_health <= 0:
            continue
        try:
            card_def = library.get_by_id(m.card_numeric_id)
        except KeyError:
            continue
        if is_dark_mage(card_def):
            count += 1
    return count


def _resolve_grant_dark_matter(
    state: GameState,
    effect: EffectDefinition,
    caster_owner: PlayerSide,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
    contract_source: Optional[str] = None,
) -> GameState:
    """GRANT_DARK_MATTER: credit the CASTER PLAYER's Dark Matter pool.

    Dark Matter pool redesign 2026-07 — minions never hold DM anymore.

    Amount rules:
      - target "owner_player" + scale_with "dark_mages": the player gains
        ``effect.amount`` per friendly LIVE Dark Mage on the board (the
        canonical shape for all migrated cards).
      - target "owner_player" without scale_with: flat ``effect.amount``.
      - legacy target "all_allies" (old per-minion grant JSONs): resolved
        as amount × friendly Dark Mage count — identical totals to the
        old per-minion semantics, restricted to true Dark Mages.

    A computed amount of 0 (no Dark Mages on board) is a silent
    identity-preserving no-op — no event is emitted.
    """
    player_idx = _player_index_for_side(caster_owner)
    amount = effect.amount
    if (
        effect.scale_with == "dark_mages"
        or effect.target in (TargetType.ALL_ALLIES, TargetType.ALL_MINIONS)
    ):
        amount = effect.amount * _count_friendly_dark_mages(
            state, caster_owner, library,
        )
    if amount <= 0:
        return state
    player = state.players[player_idx]
    new_player = player.gain_dark_matter(amount)
    if event_collector is not None:
        event_collector.collect(
            EVT_DARK_MATTER_CHANGE,
            contract_source or "trigger:on_play",
            {
                "player_idx": player_idx,
                "prev": player.dark_matter,
                "new": new_player.dark_matter,
                "delta": amount,
                "source": "grant_dark_matter",
            },
        )
    new_players = _replace_player(state.players, player_idx, new_player)
    return replace(state, players=new_players)


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
    state: GameState,
    minion: MinionInstance,
    amount: int,
    *,
    contract_source: Optional[str] = None,
) -> GameState:
    """Apply damage to a minion, reducing current_health."""
    if contract_source is not None:
        assert_phase_contract(state, contract_source)
    new_minion = replace(minion, current_health=minion.current_health - amount)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
    return replace(state, minions=new_minions)


def _apply_heal_to_minion(
    state: GameState,
    minion: MinionInstance,
    amount: int,
    library: CardLibrary,
    *,
    contract_source: Optional[str] = None,
) -> GameState:
    """Apply heal to a minion, capped at effective max HP.

    Effective max HP = CardDefinition.health + max_health_bonus so that
    flat max-HP buffs (e.g. Ratchanter's conjure_rat_and_buff) raise the
    heal ceiling too.
    """
    if contract_source is not None:
        assert_phase_contract(state, contract_source)
    card_def = library.get_by_id(minion.card_numeric_id)
    effective_max = card_def.health + minion.max_health_bonus
    new_health = min(minion.current_health + amount, effective_max)
    new_minion = replace(minion, current_health=new_health)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
    return replace(state, minions=new_minions)


def _apply_buff_attack_to_minion(
    state: GameState,
    minion: MinionInstance,
    amount: int,
    *,
    contract_source: Optional[str] = None,
) -> GameState:
    """Increase a minion's attack_bonus."""
    if contract_source is not None:
        assert_phase_contract(state, contract_source)
    new_minion = replace(minion, attack_bonus=minion.attack_bonus + amount)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
    return replace(state, minions=new_minions)


def _apply_buff_health_to_minion(
    state: GameState,
    minion: MinionInstance,
    amount: int,
    *,
    contract_source: Optional[str] = None,
) -> GameState:
    """Increase a minion's current_health (no cap -- buff_health can exceed base)."""
    if contract_source is not None:
        assert_phase_contract(state, contract_source)
    new_minion = replace(minion, current_health=minion.current_health + amount)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
    return replace(state, minions=new_minions)


def _apply_effect_to_minion(
    state: GameState,
    effect: EffectDefinition,
    minion: MinionInstance,
    library: CardLibrary,
    *,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Apply an effect to a single minion based on effect_type.

    Effect types that don't apply to a minion (CONJURE, TUTOR, RALLY,
    NEGATE, DEPLOY_SELF, LEAP, DARK_MATTER_BUFF) are silently skipped
    here — they're handled by other code paths or are informational/
    state markers that don't mutate minion stats directly. PROMOTE
    is handled by ``_apply_promote_on_death`` dispatched from
    ``resolve_effects_for_trigger``; it transforms a friendly minion
    rather than mutating the dying one, so it doesn't fit this helper.

    2026-07-08 timing audit (F4): emits EVT_MINION_HP_CHANGE at the
    mutation site whenever the minion's current_health changed, so HP
    deltas render at their causal beat instead of snapping a phase late
    on the final-state commit.
    """
    if contract_source is not None:
        assert_phase_contract(state, contract_source)
    new_state = _apply_effect_to_minion_dispatch(state, effect, minion, library)
    if event_collector is not None and new_state is not state:
        new_m = new_state.get_minion(minion.instance_id)
        # 2026-07-11 (user: "buff attack gets delayed"): diff ATTACK too —
        # attack-only buffs previously emitted nothing and combined buffs
        # lost their attack half until the drain-end snapshot, so 🗡️
        # visibly lagged 🤍 on the board.
        # Audit fix (2026-07-11): diff EVERY beat-visible field — a Cleanse
        # that only clears is_burning (the common Water Wyrm case) or only
        # restores a negative max-HP mark previously emitted NOTHING, so
        # the burning badge stayed stale until the drain-end snapshot and
        # the card's signature effect had no causal beat.
        if new_m is not None and (
            new_m.current_health != minion.current_health
            or new_m.attack_bonus != minion.attack_bonus
            or new_m.max_health_bonus != minion.max_health_bonus
            or new_m.is_burning != minion.is_burning
        ):
            event_collector.collect(
                EVT_MINION_HP_CHANGE,
                contract_source or "trigger:on_play",
                {
                    "instance_id": minion.instance_id,
                    "new_hp": new_m.current_health,
                    "delta": new_m.current_health - minion.current_health,
                    "attack_delta": new_m.attack_bonus - minion.attack_bonus,
                    "max_health_delta": (
                        new_m.max_health_bonus - minion.max_health_bonus
                    ),
                    "burning_cleared": (
                        minion.is_burning and not new_m.is_burning
                    ),
                    "owner_idx": _player_index_for_side(new_m.owner),
                    "position": list(new_m.position),
                    "cause": getattr(
                        effect.effect_type, "name", str(effect.effect_type)
                    ).lower(),
                },
            )
    return new_state


def _apply_effect_to_minion_dispatch(
    state: GameState,
    effect: EffectDefinition,
    minion: MinionInstance,
    library: CardLibrary,
) -> GameState:
    """EffectType dispatch body of ``_apply_effect_to_minion`` (split out
    so the wrapper can diff HP and emit the event — 2026-07-08 timing
    audit F4)."""
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
        # (no refresh, no stacks — the existing burn's scope is kept).
        # Burn persists until death. ``burn_scope`` (spec §7.2) comes from
        # the card's optional effect ``scope`` key; no wording = the
        # standard Burn default "owner" (ticks in the owner's Decay phase).
        if minion.is_burning:
            return state
        new_minion = replace(
            minion, is_burning=True, burn_scope=effect.scope or "owner",
        )
        new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
        return replace(state, minions=new_minions)
    elif effect.effect_type == EffectType.PASSIVE_HEAL:
        # Heal self by `amount`, capped at base health.
        return _apply_heal_to_minion(state, minion, effect.amount, library)
    elif effect.effect_type == EffectType.CLEANSE:
        # Cleanse (Water Wyrm Rally, 2026-07-11): remove the target's
        # debuffs — burning cleared, negative attack / max-HP marks reset
        # to 0. NOT a heal: current_health is untouched (a restored max-HP
        # cap just leaves room to heal back into).
        cleaned = replace(
            minion,
            is_burning=False,
            burn_scope="owner",
            attack_bonus=(
                minion.attack_bonus
                if effect.burn_only else max(0, minion.attack_bonus)
            ),
            max_health_bonus=(
                minion.max_health_bonus
                if effect.burn_only else max(0, minion.max_health_bonus)
            ),
        )
        if cleaned == minion:
            return state  # nothing to cleanse — no-op, no event churn
        new_minions = _replace_minion(state.minions, minion.instance_id, cleaned)
        return replace(state, minions=new_minions)
    elif effect.effect_type == EffectType.APPLY_BURNING:
        # Boolean burn: set is_burning=True. No-op if already burning (the
        # existing burn's scope is kept). ``burn_scope`` per spec §7.2 —
        # card's effect ``scope`` key, defaulting to "owner".
        if minion.is_burning:
            return state
        new_minion = replace(
            minion, is_burning=True, burn_scope=effect.scope or "owner",
        )
        new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
        return replace(state, minions=new_minions)
    # NOTE: GRANT_DARK_MATTER never reaches this helper — it is intercepted
    # in resolve_effect and credited to the caster PLAYER's pool (Dark
    # Matter pool redesign 2026-07). Minions never hold DM.
    # Unimplemented or non-minion-targeting effect types: skip gracefully
    return state


def _apply_effect_to_player(
    state: GameState,
    effect: EffectDefinition,
    player_idx: int,
    *,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Apply an effect to a player (DAMAGE or HEAL only).

    2026-07-08 timing audit (F4): emits EVT_PLAYER_HP_CHANGE at the
    mutation site whenever the player's hp changed (no event on a
    full-HP heal that clamps to no-op).
    """
    if contract_source is not None:
        assert_phase_contract(state, contract_source)
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
    if event_collector is not None and new_player.hp != player.hp:
        event_collector.collect(
            EVT_PLAYER_HP_CHANGE,
            contract_source or "trigger:on_play",
            {
                "player_idx": player_idx,
                "prev": player.hp,
                "new": new_player.hp,
                "delta": new_player.hp - player.hp,
                "cause": getattr(
                    effect.effect_type, "name", str(effect.effect_type)
                ).lower(),
            },
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
    *,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Resolve effect on a single target at target_pos."""
    if target_pos is None:
        # No valid target — skip effect (e.g., minion deployed with no enemies)
        return state
    minion = _find_minion_at_pos(state.minions, target_pos)
    if minion is None:
        return state  # no minion at position, state unchanged
    return _apply_effect_to_minion(
        state, effect, minion, library,
        contract_source=contract_source,
        event_collector=event_collector,
    )


def _resolve_all_enemies(
    state: GameState,
    effect: EffectDefinition,
    caster_owner: PlayerSide,
    library: CardLibrary,
    *,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Resolve effect on all enemy minions."""
    for minion in state.minions:
        if minion.owner != caster_owner:
            state = _apply_effect_to_minion(
                state, effect, minion, library,
                contract_source=contract_source,
                event_collector=event_collector,
            )
    return state


def _resolve_row(
    state: GameState,
    effect: EffectDefinition,
    caster_owner: PlayerSide,
    library: CardLibrary,
    target_pos: Optional[tuple[int, int]],
    *,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Resolve an area effect on filtered occupants of the chosen row."""
    if target_pos is None:
        return state
    target_row = target_pos[0]
    if target_row < 0 or target_row >= 5:
        return state
    target_side = effect.target_side or "all"
    for minion in state.minions:
        if minion.current_health <= 0 or minion.position[0] != target_row:
            continue
        if target_side == "enemy" and minion.owner == caster_owner:
            continue
        if target_side == "friendly" and minion.owner != caster_owner:
            continue
        state = _apply_effect_to_minion(
            state, effect, minion, library,
            contract_source=contract_source,
            event_collector=event_collector,
        )
    return state


def _resolve_adjacent(
    state: GameState,
    effect: EffectDefinition,
    caster_pos: tuple[int, int],
    library: CardLibrary,
    caster_owner: Optional[PlayerSide] = None,
    *,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
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
        state = _apply_effect_to_minion(
            state, effect, minion, library,
            contract_source=contract_source,
            event_collector=event_collector,
        )
    return state


def _resolve_self_owner(
    state: GameState,
    effect: EffectDefinition,
    caster_pos: tuple[int, int],
    caster_owner: PlayerSide,
    library: CardLibrary,
    *,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Resolve effect on the caster's minion or the owning player.

    For minion-targeting effects (BUFF_ATTACK, BUFF_HEALTH): target the minion at caster_pos.
    For player-targeting effects (DAMAGE, HEAL): target the owning player.
    """
    if effect.effect_type == EffectType.DRAW:
        # Turn-structure redesign 2026-07: overdraw-burns — a draw with a
        # full hand (MAX_HAND_SIZE) sends the card to the exhaust pile
        # (revealed) instead of fizzling. Empty deck = the draw is skipped
        # (no fatigue here; fatigue only exists at turn-start draws).
        player_idx = _player_index_for_side(caster_owner)
        player = state.players[player_idx]
        for _ in range(effect.amount):
            if player.deck:
                player, card_id, burned = player.draw_card_with_overdraw()
                # Spec: overdraw burns are REVEALED on ALL draw paths —
                # emit per-card so the client animates every draw/burn
                # (card_numeric_id on non-burn draws is redacted for the
                # opponent by view_filter; burns are public).
                if event_collector is not None:
                    event_collector.collect(
                        EVT_CARD_BURNED if burned else EVT_CARD_DRAWN,
                        contract_source or "trigger:on_play",
                        {
                            "player_idx": player_idx,
                            "source": "card_effect",
                            "card_numeric_id": card_id,
                        },
                    )
        new_players = _replace_player(state.players, player_idx, player)
        return replace(state, players=new_players)
    elif effect.effect_type in (EffectType.DAMAGE, EffectType.HEAL):
        # Target the owning player
        player_idx = _player_index_for_side(caster_owner)
        return _apply_effect_to_player(
            state, effect, player_idx,
            contract_source=contract_source,
            event_collector=event_collector,
        )
    else:
        # Target the caster's minion at caster_pos
        minion = _find_minion_at_pos(state.minions, caster_pos)
        if minion is None:
            return state  # no minion at caster_pos, unchanged
        return _apply_effect_to_minion(
            state, effect, minion, library,
            contract_source=contract_source,
            event_collector=event_collector,
        )


# ---------------------------------------------------------------------------
# Tutor (deck search)
# ---------------------------------------------------------------------------


def _enter_pending_tutor(
    state: GameState,
    card_def: CardDefinition,
    caster_owner: PlayerSide,
    library: CardLibrary,
    amount: int = 1,
    *,
    event_collector: Optional[EventStream] = None,
    origin: Optional[str] = None,
    contract_source: Optional[str] = None,
) -> GameState:
    """Phase 14.2: enter pending_tutor state.

    Computes deck indices in the caster's deck whose card matches
    `card_def.tutor_target` (string shorthand or selector dict). Does NOT
    move any card -- the pick is resolved later in action_resolver via
    TUTOR_SELECT or DECLINE_TUTOR.

    ``amount`` is how many picks the player may make before the modal
    auto-closes (e.g. To The Ratmobile has amount=2 — picker gets 2
    picks). Capped to the number of available matches.

    ``origin`` records WHERE the tutor was opened from (stored on
    ``state.pending_tutor_origin``): "summon_effect" tells the
    TUTOR_SELECT/DECLINE_TUTOR resume in action_resolver to skip the
    extra AFTER_ACTION react window (the summon's Window B already gave
    the opponent their react window — 2026-07 Red Diodebot fix).

    ``contract_source`` tags the EVT_PENDING_MODAL_OPENED emission with
    the caller's contract (defaults to "trigger:on_play" for back-compat).

    Mutex: asserts no concurrent pending_post_move_attacker_id (defense in
    depth -- tutor only fires from on_play, not from MOVE).
    """
    # Phase 14.8-01: _enter_pending_tutor inherits its caller's contract
    # (on_play from action:play_card path; on_death-fired tutor would
    # inherit trigger:on_death). The caller has already asserted; this
    # function does not re-tag because it has no fixed source.
    if not card_def.tutor_target:
        return state

    assert state.pending_post_move_attacker_id is None, (
        "Cannot enter pending_tutor while pending_post_move_attacker_id is set"
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

    if state.pending_tutor_player_idx is not None:
        # Latent double-tutor collision: two TUTOR effects resolving in
        # the SAME LIFO react-chain drain (e.g. two Tree Wyrm reacts).
        # This used to be a hard `assert` — a chain that legally played
        # two tutors crashed the engine. There is only ONE pending_tutor
        # slot, so:
        #   - Same player + identical match set (same tutor filter):
        #     MERGE by extending the remaining pick count — exactly the
        #     rules-correct outcome for stacked same-card tutors.
        #   - Anything else (different player / different filter):
        #     the later tutor fizzles silently (spec §7.3 no-op) rather
        #     than crashing mid-chain.
        if (
            state.pending_tutor_player_idx == player_idx
            and not state.pending_tutor_is_conjure
            and tuple(matches) == state.pending_tutor_matches
            and matches
        ):
            new_remaining = min(
                state.pending_tutor_remaining + max(1, amount),
                len(matches),
            )
            # Flag already set by the first tutor in the chain; keep it.
            return replace(state, pending_tutor_remaining=new_remaining)
        return state

    if not matches:
        # No candidates -- silently no-op (caller proceeds to react window).
        return state

    # Mark the caster as having tutored this turn — ReactCondition
    # OPPONENT_TUTORS (Tree Wyrm) reads this in the react window that opens
    # once this tutor resolves. Set at modal-open (a tutor is happening),
    # before the caster picks. (2026-07-09)
    tutoring_players = _replace_player(
        state.players, player_idx,
        replace(state.players[player_idx], tutored_this_turn=True),
    )
    remaining = max(1, min(amount, len(matches)))
    new_state = replace(
        state,
        players=tutoring_players,
        pending_tutor_player_idx=player_idx,
        pending_tutor_matches=tuple(matches),
        pending_tutor_remaining=remaining,
        pending_tutor_origin=origin,
    )
    # Phase 14.8-03a: pending modal opened — client gates eventQueue.
    if event_collector is not None:
        event_collector.collect(
            EVT_PENDING_MODAL_OPENED,
            contract_source or "trigger:on_play",
            {
                "modal_kind": "tutor_select",
                "owner_idx": player_idx,
                "options_count": len(matches),
                "remaining": remaining,
            },
            requires_decision=True,
        )
    return new_state


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
    *,
    source_minion_id: Optional[int] = None,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
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
        source_minion_id: Phase 14.7-06 — when the effect source is a
            minion (triggered effect from an on_death / start_of_turn /
            end_of_turn / on_summon queue entry, or an activated ability),
            pass the minion's instance_id so the fizzle gate can re-
            validate source liveness. Leave None for magic casts and
            react-card effects where the source is a player / card.
        contract_source: Phase 14.8-01 — the "<category>:<name>" string
            identifying which contract authorized this resolution
            (e.g. "trigger:on_play", "trigger:on_death",
            "action:play_react"). When supplied, the engine asserts the
            contract is legal in state.phase. Default None preserves
            back-compat at mode=off; the invariant test in plan 14.8-02
            will surface any caller that didn't pass a source.

    Returns:
        New GameState with effect applied. Returns ``state`` unchanged
        (identity-preserving) when the fizzle gate rejects the target.

    Raises:
        ValueError: If target_pos is None for SINGLE_TARGET effects.
    """
    if contract_source is not None:
        assert_phase_contract(state, contract_source)
    # Phase 14.7-06: Fizzle gate. An effect whose target is no longer
    # valid at resolution time fizzles SILENTLY — return the incoming
    # state unchanged (identity-preserving so callers can detect no-op
    # via ``state is prev_state``).
    if not _validate_target_at_resolve_time(
        state, effect, caster_pos, source_minion_id, target_pos,
    ):
        return state
    # target_side also constrains SINGLE_TARGET effects.  It was originally
    # introduced for ROW occupancy filters, but friendly utility magic needs
    # the same authoritative resolution-time check (not only a UI/legal-mask
    # hint).  Omitted keeps the legacy resolver behaviour; legal enumeration
    # still defaults ordinary targeted magic to enemies.
    if effect.target == TargetType.SINGLE_TARGET and effect.target_side:
        target_minion = _find_minion_at_pos(state.minions, target_pos)
        if target_minion is None:
            return state
        if effect.target_side == "friendly" and target_minion.owner != caster_owner:
            return state
        if effect.target_side == "enemy" and target_minion.owner == caster_owner:
            return state
    # Dark Matter pool redesign 2026-07: GRANT_DARK_MATTER is intercepted
    # here — it ALWAYS credits the caster PLAYER's pool, never a minion,
    # regardless of the (possibly legacy) target on the JSON effect.
    if effect.effect_type == EffectType.GRANT_DARK_MATTER:
        return _resolve_grant_dark_matter(
            state, effect, caster_owner, library,
            event_collector=event_collector,
            contract_source=contract_source,
        )

    # Scale amount if scale_with is set. Dark Matter pool redesign 2026-07:
    # BOTH spellings — "dark_matter" (legacy) and "player_dark_matter" —
    # read the CASTER PLAYER's Dark Matter pool (Player.dark_matter). The
    # old caster-minion own-stacks lookup and the per-target ALL_ALLIES
    # scaling are gone: minions never hold DM anymore.
    scaled_effect = effect
    _dm_scaled = False  # True when a scale_with computed a flat amount → 0 skips AFTER multiplier
    if effect.scale_with in ("dark_matter", "player_dark_matter"):
        # Dead-source fizzle still applies (Dark Matter Battery rule): a
        # queued trigger whose SOURCE minion died before resolution
        # fizzles silently — the aura dies with its source.
        if source_minion_id is not None:
            src = state.get_minion(source_minion_id)
            if src is None or src.current_health <= 0:
                return state
        pool = state.players[_player_index_for_side(caster_owner)].dark_matter
        scaled_effect = replace(effect, amount=effect.amount + pool)
        _dm_scaled = True

    # Placement condition multiplier (e.g. "triple if placed in front of dark ranged")
    if scaled_effect.placement_condition and scaled_effect.condition_multiplier > 1:
        if _check_placement_condition(state, caster_pos, caster_owner, scaled_effect.placement_condition, library):
            scaled_effect = replace(scaled_effect, amount=scaled_effect.amount * scaled_effect.condition_multiplier)

    # DM-scaled effects with a final amount of 0 skip silently (identity-
    # preserving no-op, matching the fizzle contract). This check runs
    # AFTER the placement multiplier so a nonzero base amount on a
    # condition card still multiplies before being tested.
    if _dm_scaled and scaled_effect.amount <= 0:
        return state

    if scaled_effect.target == TargetType.SINGLE_TARGET:
        return _resolve_single_target(
            state, scaled_effect, library, target_pos,
            contract_source=contract_source,
            event_collector=event_collector,
        )
    elif scaled_effect.target == TargetType.ALL_ENEMIES:
        return _resolve_all_enemies(
            state, scaled_effect, caster_owner, library,
            contract_source=contract_source,
            event_collector=event_collector,
        )
    elif scaled_effect.target == TargetType.ROW:
        return _resolve_row(
            state, scaled_effect, caster_owner, library, target_pos,
            contract_source=contract_source,
            event_collector=event_collector,
        )
    elif scaled_effect.target == TargetType.ADJACENT:
        return _resolve_adjacent(
            state, scaled_effect, caster_pos, library, caster_owner,
            contract_source=contract_source,
            event_collector=event_collector,
        )
    elif scaled_effect.target == TargetType.SELF_OWNER:
        return _resolve_self_owner(
            state, scaled_effect, caster_pos, caster_owner, library,
            contract_source=contract_source,
            event_collector=event_collector,
        )
    elif scaled_effect.target == TargetType.OPPONENT_PLAYER:
        opp_idx = 1 - _player_index_for_side(caster_owner)
        return _apply_effect_to_player(
            state, scaled_effect, opp_idx,
            contract_source=contract_source,
            event_collector=event_collector,
        )
    elif scaled_effect.target == TargetType.OWNER_PLAYER:
        # Dark Matter pool redesign 2026-07: direct-to-caster-player
        # target. GRANT_DARK_MATTER was already intercepted above; the
        # remaining player-shaped effects (DAMAGE / HEAL) apply to the
        # casting player.
        return _apply_effect_to_player(
            state, scaled_effect, _player_index_for_side(caster_owner),
            contract_source=contract_source,
            event_collector=event_collector,
        )
    elif scaled_effect.target == TargetType.ALL_MINIONS:
        for minion in state.minions:
            if minion.current_health <= 0:
                continue
            if scaled_effect.target_tribe or scaled_effect.target_element:
                card_def = library.get_by_id(minion.card_numeric_id)
                tribe_match = bool(
                    scaled_effect.target_tribe
                    and _effect_tribe_matches(card_def, scaled_effect.target_tribe)
                )
                element_match = bool(
                    scaled_effect.target_element
                    and card_def.element.name.lower() == scaled_effect.target_element.lower()
                )
                if not (tribe_match or element_match):
                    continue
            state = _apply_effect_to_minion(
                state, scaled_effect, minion, library,
                contract_source=contract_source,
                event_collector=event_collector,
            )
        return state
    elif scaled_effect.target == TargetType.ALL_ALLIES:
        for minion in state.minions:
            if minion.owner != caster_owner or minion.current_health <= 0:
                continue
            if scaled_effect.target_tribe:
                card_def = library.get_by_id(minion.card_numeric_id)
                if not _effect_tribe_matches(card_def, scaled_effect.target_tribe):
                    continue
            state = _apply_effect_to_minion(
                state, scaled_effect, minion, library,
                contract_source=contract_source,
                event_collector=event_collector,
            )
        return state
    else:
        raise ValueError(f"Unknown target type: {scaled_effect.target}")


def resolve_effects_for_trigger(
    state: GameState,
    trigger: TriggerType,
    minion: MinionInstance,
    library: CardLibrary,
    target_pos: Optional[tuple[int, int]] = None,
    *,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Resolve all effects on a minion's card that match the given trigger.

    Effects are processed in the order they appear in the card's effects tuple.

    Args:
        state: Current game state.
        trigger: Which trigger to filter for.
        minion: The minion whose card effects to check.
        library: CardLibrary for card definition lookup.
        target_pos: Optional target position for SINGLE_TARGET effects.
        contract_source: Phase 14.8-01 — when supplied, asserts the
            contract is legal in state.phase. When None, defaults to
            ``f"trigger:{trigger.name.lower()}"`` (the canonical source
            for trigger-driven resolution) so callers that don't pass an
            explicit override still get tagged.

    Returns:
        New GameState with all matching effects applied in order.
    """
    if contract_source is None:
        contract_source = f"trigger:{trigger.name.lower()}"
    assert_phase_contract(state, contract_source)
    card_def = library.get_by_id(minion.card_numeric_id)
    matching_effects = [e for e in card_def.effects if e.trigger == trigger]

    if not matching_effects:
        return state  # no matching effects, return unchanged

    for effect in matching_effects:
        if effect.effect_type == EffectType.TUTOR:
            state = _enter_pending_tutor(
                state, card_def, minion.owner, library,
                amount=max(1, effect.amount or 1),
                event_collector=event_collector,
                origin=(
                    "summon_effect"
                    if trigger == TriggerType.ON_SUMMON
                    else contract_source
                ),
                contract_source=contract_source,
            )
        elif effect.effect_type == EffectType.CONJURE:
            state = _resolve_conjure(
                state, card_def, minion.owner, library,
                contract_source=contract_source,
                event_collector=event_collector,
            )
        elif effect.effect_type == EffectType.RALLY_FORWARD:
            state = _apply_rally_forward(
                state, minion, event_collector=event_collector,
            )
        elif effect.effect_type == EffectType.PROMOTE:
            state = _apply_promote_on_death(
                state, minion.card_numeric_id, minion.owner, library,
                event_collector=event_collector,
            )
        else:
            # Phase 14.7-06: pass source_minion_id so the fizzle gate
            # can re-validate source liveness for ADJACENT / SELF_OWNER
            # effects. The minion instance passed in is always the
            # source of the trigger.
            state = resolve_effect(
                state, effect, minion.position, minion.owner, library, target_pos,
                source_minion_id=minion.instance_id,
                contract_source=contract_source,
                event_collector=event_collector,
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
    assert_phase_contract(state, "trigger:on_death")
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
                origin="trigger:on_death",
                contract_source="trigger:on_death",
            )
        elif effect.effect_type == EffectType.CONJURE:
            state = _resolve_conjure(
                state, card_def, owner, library,
                contract_source="trigger:on_death",
            )
        elif effect.effect_type == EffectType.RALLY_FORWARD:
            # RALLY_FORWARD on death would need a mover reference; no live
            # card uses it, but keep the dispatch symmetric with
            # resolve_effects_for_trigger so a future card can slot in.
            pass
        else:
            state = resolve_effect(
                state, effect, position, owner, library, target_pos=None,
                contract_source="trigger:on_death",
            )

    return state, -1


def apply_death_target_pick(
    state: GameState,
    target_pos: tuple[int, int],
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
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
    assert_phase_contract(state, "action:death_target_pick")
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
        # PROMOTE beat — see _apply_promote_on_death (silent promotions
        # desynced the client render).
        if event_collector is not None:
            event_collector.collect(
                EVT_MINION_TRANSFORMED,
                "action:death_target_pick",
                {
                    "instance_id": picked.instance_id,
                    "from_card_numeric_id": picked.card_numeric_id,
                    "to_card_numeric_id": target.card_numeric_id,
                    "owner_idx": target.owner_idx,
                    "position": list(picked.position),
                    "new_hp": card_def.health,
                },
            )
    else:
        # Future-proof: other effect types that could use this modal path.
        state = resolve_effect(
            state,
            effect,
            caster_pos=(0, 0),
            caster_owner=PlayerSide(target.owner_idx),
            library=library,
            target_pos=target_pos,
            contract_source="action:death_target_pick",
        )

    # Phase 14.8-05: pending_death_queue field DELETED — on_death effects
    # route exclusively through the PendingTrigger priority queue since
    # 14.7-05b. The defensive queue-advance code here was a no-op guard
    # for legacy in-flight queue entries that never materialized.
    state = replace(
        state,
        pending_death_target=None,
    )
    return state


def _apply_promote_on_death(
    state: GameState,
    dying_card_numeric_id: int,
    dying_owner: PlayerSide,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
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
        burn_scope="owner",
    )
    new_minions = _replace_minion(state.minions, chosen.instance_id, promoted)
    # PROMOTE beat (user 2026-07-11 GT rat report): promotions resolved
    # SILENTLY — no event — so the client rendered a mix of stale beats
    # and the drain-end snapshot (a freshly summoned Common Rat showing
    # Giant Rat stats over its old HP). EVT_MINION_TRANSFORMED gives the
    # swap its own animated, logged beat like Reanimated Bones.
    if event_collector is not None:
        event_collector.collect(
            EVT_MINION_TRANSFORMED,
            "trigger:on_death",
            {
                "instance_id": chosen.instance_id,
                "from_card_numeric_id": target_card_numeric_id,
                "to_card_numeric_id": dying_card_numeric_id,
                "owner_idx": int(dying_owner),
                "position": list(chosen.position),
                "new_hp": dying_card_def.health,
            },
        )
    return replace(state, minions=new_minions)


def _apply_rally_forward(
    state: GameState,
    mover: MinionInstance,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """MARCH (march_forward, ex-RALLY_FORWARD): advance every other friendly
    minion with the same card_numeric_id forward 1 tile in its column, if
    the destination is in-bounds and empty. Mirrors the tensor engine
    implementation (``tensor_engine/actions.py::_apply_rally_forward``).

    The mover itself is excluded. Minions whose forward tile is blocked
    or off the board are left in place.

    2026-07 card-audit fix (Furryroach): emits one EVT_MINION_MOVED per
    marched ally so the client eventQueue animates the swarm advance
    instead of snapping positions on the final-state commit.
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
        if event_collector is not None:
            event_collector.collect(
                EVT_MINION_MOVED,
                "trigger:on_move",
                {
                    "instance_id": m.instance_id,
                    "from": [src_row, src_col],
                    "to": [dst_row, src_col],
                    "owner_idx": _player_index_for_side(m.owner),
                    "cause": "march",
                },
            )
    return replace(state, board=new_board, minions=tuple(new_minions_list))


def _resolve_conjure(
    state: GameState,
    card_def: CardDefinition,
    caster_owner: PlayerSide,
    library: CardLibrary,
    *,
    contract_source: Optional[str] = None,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Conjure: add a copy of summon_token_target card to the caster's hand.

    Unlike tutor (which searches the deck), conjure creates a card from outside
    the deck. Used by Ratchanter and similar 'summoner' minions.
    """
    if contract_source is not None:
        assert_phase_contract(state, contract_source)
    if not card_def.summon_token_target:
        return state
    try:
        target_numeric_id = library.get_numeric_id(card_def.summon_token_target)
    except KeyError:
        return state
    player_idx = _player_index_for_side(caster_owner)
    player = state.players[player_idx]
    # Turn-structure redesign 2026-07: overdraw-burns — a full hand
    # (MAX_HAND_SIZE) sends the conjured card to the exhaust pile
    # (revealed) instead of skipping the conjure.
    new_player, _burned = player.add_to_hand_with_overdraw(target_numeric_id)
    if event_collector is not None:
        # 2026-07-08 timing audit (F2): the non-burn branch previously
        # emitted NOTHING — the conjured card appeared in hand only at
        # the drain-end snapshot. Emit EVT_CARD_DRAWN so the client
        # animates the hand add at its causal beat. Burns stay on
        # EVT_CARD_BURNED (public, never redacted).
        event_collector.collect(
            EVT_CARD_BURNED if _burned else EVT_CARD_DRAWN,
            contract_source or "trigger:on_play",
            {
                "player_idx": player_idx,
                "card_numeric_id": target_numeric_id,
                "source": "conjure",
            },
        )
    new_players = _replace_player(state.players, player_idx, new_player)
    return replace(state, players=new_players)
