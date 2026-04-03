"""Batched effect resolution via CardTable lookup.

All effects are resolved as tensor operations over the batch dimension.
The loop over MAX_EFFECTS_PER_CARD is a fixed 3-iteration Python loop
(not over batch), which is fine for torch.compile.
"""

from __future__ import annotations

import torch

from grid_tactics.tensor_engine.constants import (
    GRID_COLS,
    MAX_EFFECTS_PER_CARD,
    MAX_MINIONS,
    STARTING_HP,
)


def apply_effects_batch(
    state,  # TensorGameState
    card_ids: torch.Tensor,        # [N] which card triggered
    trigger: int,                  # TriggerType enum value to match
    caster_owners: torch.Tensor,   # [N] int32 (0 or 1)
    caster_slots: torch.Tensor,    # [N] int32 (minion slot of caster, -1 if no minion)
    target_flat_pos: torch.Tensor,  # [N] int32 (flat board pos for SINGLE_TARGET, -1 if none)
    card_table,                    # CardTable
    mask: torch.Tensor,            # [N] bool -- which games to apply effects to
):
    """Apply all matching-trigger effects from cards, batched across N games.

    Iterates over effect slots (MAX_EFFECTS_PER_CARD), not over batch.
    """
    N = card_ids.shape[0]
    device = card_ids.device
    # Clamp card_ids to valid range for indexing (invalid entries masked out)
    safe_ids = card_ids.clamp(min=0)

    for eff_idx in range(MAX_EFFECTS_PER_CARD):
        # Look up effect properties from card_table
        etype = card_table.effect_type[safe_ids, eff_idx]       # [N]
        etrigger = card_table.effect_trigger[safe_ids, eff_idx]  # [N]
        etarget = card_table.effect_target[safe_ids, eff_idx]   # [N]
        eamount = card_table.effect_amount[safe_ids, eff_idx]   # [N]

        # Only active if: trigger matches, effect exists, and game is masked
        active = mask & (etrigger == trigger) & (eff_idx < card_table.num_effects[safe_ids])

        if not active.any():
            continue

        # Dispatch by effect type (DAMAGE=0, HEAL=1, BUFF_ATTACK=2, BUFF_HEALTH=3)
        # NEGATE=4 and DEPLOY_SELF=5 are handled elsewhere
        _apply_damage(state, active & (etype == 0), etarget, eamount, caster_owners, caster_slots, target_flat_pos, card_table)
        _apply_heal(state, active & (etype == 1), etarget, eamount, caster_owners, caster_slots, target_flat_pos, card_table)
        _apply_buff_attack(state, active & (etype == 2), etarget, eamount, caster_owners, caster_slots)
        _apply_buff_health(state, active & (etype == 3), etarget, eamount, caster_owners, caster_slots)


def _find_minion_slot_at_pos(state, flat_pos: torch.Tensor) -> torch.Tensor:
    """Find the minion slot index at a given flat board position.

    Returns [N] int32, -1 if no minion.
    """
    row = flat_pos // GRID_COLS  # [N]
    col = flat_pos % GRID_COLS   # [N]
    # Clamp to valid range
    row = row.clamp(0, 4)
    col = col.clamp(0, 4)
    N = flat_pos.shape[0]
    arange_n = torch.arange(N, device=flat_pos.device)
    return state.board[arange_n, row, col]  # [N] minion slot index or -1


def _apply_damage(state, active, etarget, eamount, caster_owners, caster_slots, target_flat_pos, card_table):
    """Apply DAMAGE effect to targets."""
    if not active.any():
        return
    N = active.shape[0]
    device = active.device
    arange_n = torch.arange(N, device=device)

    # SINGLE_TARGET (0): damage minion at target_flat_pos
    single = active & (etarget == 0)
    if single.any():
        slot = _find_minion_slot_at_pos(state, target_flat_pos)
        valid = single & (slot >= 0)
        if valid.any():
            safe_slot = slot.clamp(min=0)
            dmg = eamount * valid.int()
            state.minion_health[arange_n, safe_slot] -= dmg

    # ALL_ENEMIES (1): damage all enemy minions
    all_enemies = active & (etarget == 1)
    if all_enemies.any():
        # For each minion slot, check if alive and enemy
        for s in range(MAX_MINIONS):
            is_enemy = state.minion_alive[:, s] & (state.minion_owner[:, s] != caster_owners)
            hit = all_enemies & is_enemy
            if hit.any():
                state.minion_health[:, s] -= eamount * hit.int()

    # ADJACENT (2): damage minions adjacent to caster
    adj = active & (etarget == 2)
    if adj.any():
        _apply_to_adjacent(state, adj, eamount, caster_slots, card_table, damage=True)

    # SELF_OWNER (3): damage owning player HP
    self_owner = active & (etarget == 3)
    if self_owner.any():
        for p in range(2):
            is_p = self_owner & (caster_owners == p)
            if is_p.any():
                state.player_hp[:, p] -= eamount * is_p.int()


def _apply_heal(state, active, etarget, eamount, caster_owners, caster_slots, target_flat_pos, card_table):
    """Apply HEAL effect to targets."""
    if not active.any():
        return
    N = active.shape[0]
    device = active.device
    arange_n = torch.arange(N, device=device)

    # SINGLE_TARGET (0)
    single = active & (etarget == 0)
    if single.any():
        slot = _find_minion_slot_at_pos(state, target_flat_pos)
        valid = single & (slot >= 0)
        if valid.any():
            safe_slot = slot.clamp(min=0)
            # Get base health cap from card_table
            minion_cid = state.minion_card_id[arange_n, safe_slot].clamp(min=0)
            base_hp = card_table.health[minion_cid]
            new_hp = torch.min(
                state.minion_health[arange_n, safe_slot] + eamount,
                base_hp,
            )
            old_hp = state.minion_health[arange_n, safe_slot]
            state.minion_health[arange_n, safe_slot] = torch.where(valid, new_hp, old_hp)

    # ALL_ENEMIES (1) - heal all enemy minions (unusual but handle it)
    all_enemies = active & (etarget == 1)
    if all_enemies.any():
        for s in range(MAX_MINIONS):
            is_enemy = state.minion_alive[:, s] & (state.minion_owner[:, s] != caster_owners)
            hit = all_enemies & is_enemy
            if hit.any():
                minion_cid = state.minion_card_id[:, s].clamp(min=0)
                base_hp = card_table.health[minion_cid]
                new_hp = torch.min(state.minion_health[:, s] + eamount, base_hp)
                state.minion_health[:, s] = torch.where(hit, new_hp, state.minion_health[:, s])

    # SELF_OWNER (3): heal owning player HP
    self_owner = active & (etarget == 3)
    if self_owner.any():
        for p in range(2):
            is_p = self_owner & (caster_owners == p)
            if is_p.any():
                new_hp = torch.min(
                    state.player_hp[:, p] + eamount,
                    torch.tensor(STARTING_HP, device=device),
                )
                state.player_hp[:, p] = torch.where(is_p, new_hp, state.player_hp[:, p])


def _apply_buff_attack(state, active, etarget, eamount, caster_owners, caster_slots):
    """Apply BUFF_ATTACK to SELF_OWNER target (caster's minion)."""
    if not active.any():
        return
    # SELF_OWNER (3): buff the caster minion's attack
    self_owner = active & (etarget == 3)
    if self_owner.any():
        N = active.shape[0]
        arange_n = torch.arange(N, device=active.device)
        safe_slot = caster_slots.clamp(min=0)
        valid = self_owner & (caster_slots >= 0) & state.minion_alive[arange_n, safe_slot]
        if valid.any():
            state.minion_atk_bonus[arange_n, safe_slot] += eamount * valid.int()


def _apply_buff_health(state, active, etarget, eamount, caster_owners, caster_slots):
    """Apply BUFF_HEALTH to SELF_OWNER target (caster's minion, no cap)."""
    if not active.any():
        return
    self_owner = active & (etarget == 3)
    if self_owner.any():
        N = active.shape[0]
        arange_n = torch.arange(N, device=active.device)
        safe_slot = caster_slots.clamp(min=0)
        valid = self_owner & (caster_slots >= 0) & state.minion_alive[arange_n, safe_slot]
        if valid.any():
            state.minion_health[arange_n, safe_slot] += eamount * valid.int()


def _apply_to_adjacent(state, active, eamount, caster_slots, card_table, damage=True):
    """Apply effect to all minions adjacent to caster position."""
    N = active.shape[0]
    device = active.device

    safe_slot = caster_slots.clamp(min=0)
    arange_n = torch.arange(N, device=device)
    caster_row = state.minion_row[arange_n, safe_slot]
    caster_col = state.minion_col[arange_n, safe_slot]
    caster_flat = caster_row * GRID_COLS + caster_col  # [N]

    # For each minion slot, check if adjacent to caster
    for s in range(MAX_MINIONS):
        if not state.minion_alive[:, s].any():
            continue
        m_row = state.minion_row[:, s]
        m_col = state.minion_col[:, s]
        m_flat = m_row * GRID_COLS + m_col
        # Use chebyshev distance == 1 for all adjacent (ortho + diagonal)
        safe_caster_flat = caster_flat.clamp(0, 24)
        safe_m_flat = m_flat.clamp(0, 24)
        is_adj = card_table.distance_chebyshev[safe_caster_flat, safe_m_flat] == 1
        hit = active & state.minion_alive[:, s] & is_adj & (caster_slots >= 0)
        if hit.any():
            if damage:
                state.minion_health[:, s] -= eamount * hit.int()
            else:
                # Heal adjacent (unusual but possible)
                minion_cid = state.minion_card_id[:, s].clamp(min=0)
                base_hp = card_table.health[minion_cid]
                new_hp = torch.min(state.minion_health[:, s] + eamount, base_hp)
                state.minion_health[:, s] = torch.where(hit, new_hp, state.minion_health[:, s])
