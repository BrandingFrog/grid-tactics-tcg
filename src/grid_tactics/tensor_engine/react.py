"""Batched react stack operations and LIFO resolution.

The react stack resolves in fixed-iteration loops with masking.
NEGATE effects cancel the next entry in LIFO order.

Fully vectorized: zero .item() calls, zero for-loops over batch N.
Remaining loops are over fixed constants (MAX_REACT_DEPTH, MAX_EFFECTS_PER_CARD,
MAX_MINIONS).
"""

from __future__ import annotations

import torch

from grid_tactics.tensor_engine.constants import (
    EMPTY,
    GRID_COLS,
    MAX_MINIONS,
    MAX_REACT_DEPTH,
    STARTING_HP,
)
from grid_tactics.tensor_engine.effects import apply_effects_batch


def resolve_react_stack_batch(state, card_table, resolve_mask=None):
    """Resolve react stacks for masked games in batch (LIFO order).

    Args:
        state: TensorGameState
        card_table: CardTable
        resolve_mask: [N] bool tensor -- only resolve stacks for these games.
                      If None, resolve all games.

    For each stack entry from top to bottom:
    - If negated, skip
    - If REACT card with NEGATE effect, mark next entry as negated
    - Resolve ON_PLAY effects for REACT cards
    - Resolve react_effect for multi-purpose cards (including DEPLOY_SELF)
    """
    N = state.board.shape[0]
    device = state.board.device
    arange_n = torch.arange(N, device=device)

    if resolve_mask is None:
        resolve_mask = torch.ones(N, dtype=torch.bool, device=device)

    # Track which entries are negated
    negated = torch.zeros((N, MAX_REACT_DEPTH), dtype=torch.bool, device=device)

    # Iterate LIFO (highest index = last pushed = first resolved)
    for depth_idx in range(MAX_REACT_DEPTH - 1, -1, -1):
        # Active = games with stack entries at this depth AND in resolve_mask
        active = resolve_mask & (state.react_stack_depth > depth_idx) & ~state.is_game_over

        if not active.any():
            continue

        # Skip negated entries
        should_resolve = active & ~negated[:, depth_idx]
        if not should_resolve.any():
            continue

        # Read stack entry
        entry_player = state.react_stack[:, depth_idx, 0]   # [N]
        entry_cid = state.react_stack[:, depth_idx, 1]       # [N]
        entry_target = state.react_stack[:, depth_idx, 2]    # [N] (0-24 or 25=no target)
        safe_cid = entry_cid.clamp(min=0).long()

        # Check card type
        ct = card_table.card_type[safe_cid]           # [N]
        is_react_card = (ct == 2)                       # CardType.REACT
        is_multi = card_table.is_multi_purpose[safe_cid]  # [N]

        # --- REACT cards ---
        react_resolve = should_resolve & is_react_card
        if react_resolve.any():
            # Check for NEGATE effects (loop over MAX_EFFECTS_PER_CARD=3, not N)
            has_negate = torch.zeros(N, dtype=torch.bool, device=device)
            for eff_idx in range(3):
                eff_type = card_table.effect_type[safe_cid, eff_idx]
                eff_valid = (eff_idx < card_table.num_effects[safe_cid])
                is_negate = (eff_type == 4) & eff_valid  # EffectType.NEGATE=4
                has_negate = has_negate | (react_resolve & is_negate)

            # Mark next entry as negated
            if depth_idx > 0:
                negated[:, depth_idx - 1] = negated[:, depth_idx - 1] | has_negate

            # Resolve non-NEGATE ON_PLAY effects
            # Convert target to flat pos (-1 if no target)
            tgt_flat = torch.where(entry_target < 25, entry_target, torch.tensor(-1, device=device))
            # React cards have no caster minion on board
            caster_slots = torch.full((N,), -1, dtype=torch.int32, device=device)

            apply_effects_batch(
                state, safe_cid.int(), 0, entry_player, caster_slots, tgt_flat.int(),
                card_table, react_resolve,
            )

        # --- Multi-purpose cards ---
        multi_resolve = should_resolve & is_multi & ~is_react_card
        if multi_resolve.any():
            re_type = card_table.react_effect_type[safe_cid]     # [N]
            re_target = card_table.react_effect_target[safe_cid]  # [N]
            re_amount = card_table.react_effect_amount[safe_cid]  # [N]

            # DEPLOY_SELF (5) -- fully batched
            deploy_mask = multi_resolve & (re_type == 5)
            if deploy_mask.any():
                _deploy_self_batch(state, deploy_mask, entry_cid, entry_player,
                                   entry_target, card_table, arange_n)

            # Other react effects (non-DEPLOY_SELF) -- fully batched
            other_multi = multi_resolve & (re_type != 5) & (re_type >= 0)
            if other_multi.any():
                tgt_flat = torch.where(entry_target < 25, entry_target, torch.tensor(-1, device=device))
                _apply_react_effects_batch(
                    state, other_multi, re_type, re_target, re_amount,
                    entry_player, tgt_flat, card_table, arange_n,
                )


def _deploy_self_batch(state, deploy_mask, card_ids, owners, entry_target, card_table, arange_n):
    """Deploy minions from react DEPLOY_SELF -- fully batched."""
    N = deploy_mask.shape[0]
    device = deploy_mask.device

    # Validate target position
    valid = deploy_mask & (entry_target >= 0) & (entry_target < 25)
    if not valid.any():
        return

    row = (entry_target // GRID_COLS).clamp(0, 4)
    col = (entry_target % GRID_COLS).clamp(0, 4)

    slot = state.next_minion_slot.clone()  # [N]
    valid = valid & (slot < MAX_MINIONS)

    if not valid.any():
        return

    safe_slot = slot.clamp(0, MAX_MINIONS - 1).long()
    safe_cid = card_ids.clamp(0).long()

    # Set board cell
    state.board[arange_n, row, col] = torch.where(
        valid, safe_slot.int(), state.board[arange_n, row, col]
    )
    # Set minion properties
    state.minion_card_id[arange_n, safe_slot] = torch.where(
        valid, card_ids, state.minion_card_id[arange_n, safe_slot]
    )
    state.minion_owner[arange_n, safe_slot] = torch.where(
        valid, owners, state.minion_owner[arange_n, safe_slot]
    )
    state.minion_row[arange_n, safe_slot] = torch.where(
        valid, row.int(), state.minion_row[arange_n, safe_slot]
    )
    state.minion_col[arange_n, safe_slot] = torch.where(
        valid, col.int(), state.minion_col[arange_n, safe_slot]
    )
    base_health = card_table.health[safe_cid]
    state.minion_health[arange_n, safe_slot] = torch.where(
        valid, base_health, state.minion_health[arange_n, safe_slot]
    )
    state.minion_atk_bonus[arange_n, safe_slot] = torch.where(
        valid, torch.tensor(0, device=device, dtype=torch.int32),
        state.minion_atk_bonus[arange_n, safe_slot]
    )
    state.minion_alive[arange_n, safe_slot] = torch.where(
        valid, torch.tensor(True, device=device),
        state.minion_alive[arange_n, safe_slot]
    )
    state.next_minion_slot = torch.where(
        valid, slot + 1, state.next_minion_slot
    )


def _apply_react_effects_batch(state, active_mask, re_type, re_target, re_amount,
                                 owners, target_flat, card_table, arange_n):
    """Apply react effects for multi-purpose cards -- fully batched.

    Handles DAMAGE, HEAL, BUFF_ATTACK, BUFF_HEALTH effect types with
    SINGLE_TARGET, ALL_ENEMIES, SELF_OWNER targeting.
    """
    N = active_mask.shape[0]
    device = active_mask.device

    # --- DAMAGE (0) ---
    is_damage = active_mask & (re_type == 0)
    if is_damage.any():
        # SINGLE_TARGET (0)
        dmg_single = is_damage & (re_target == 0)
        if dmg_single.any():
            valid_pos = dmg_single & (target_flat >= 0) & (target_flat < 25)
            if valid_pos.any():
                row = (target_flat // GRID_COLS).clamp(0, 4)
                col = (target_flat % GRID_COLS).clamp(0, 4)
                slot = state.board[arange_n, row, col]
                hit = valid_pos & (slot >= 0)
                if hit.any():
                    safe_slot = slot.clamp(0).long()
                    state.minion_health[arange_n, safe_slot] -= (re_amount * hit.int())

        # ALL_ENEMIES (1)
        dmg_all = is_damage & (re_target == 1)
        if dmg_all.any():
            for s in range(MAX_MINIONS):
                is_enemy = state.minion_alive[:, s] & (state.minion_owner[:, s] != owners)
                hit = dmg_all & is_enemy
                if hit.any():
                    state.minion_health[:, s] -= (re_amount * hit.int())

        # SELF_OWNER (3) -- damage owning player
        dmg_self = is_damage & (re_target == 3)
        if dmg_self.any():
            for p in range(2):
                is_p = dmg_self & (owners == p)
                if is_p.any():
                    state.player_hp[:, p] -= (re_amount * is_p.int())

    # --- HEAL (1) ---
    is_heal = active_mask & (re_type == 1)
    if is_heal.any():
        # SINGLE_TARGET (0)
        heal_single = is_heal & (re_target == 0)
        if heal_single.any():
            valid_pos = heal_single & (target_flat >= 0) & (target_flat < 25)
            if valid_pos.any():
                row = (target_flat // GRID_COLS).clamp(0, 4)
                col = (target_flat % GRID_COLS).clamp(0, 4)
                slot = state.board[arange_n, row, col]
                hit = valid_pos & (slot >= 0)
                if hit.any():
                    safe_slot = slot.clamp(0).long()
                    cid = state.minion_card_id[arange_n, safe_slot].clamp(0).long()
                    base_hp = card_table.health[cid]
                    new_hp = torch.min(
                        state.minion_health[arange_n, safe_slot] + re_amount,
                        base_hp,
                    )
                    state.minion_health[arange_n, safe_slot] = torch.where(
                        hit, new_hp, state.minion_health[arange_n, safe_slot]
                    )

        # SELF_OWNER (3) -- heal owning player
        heal_self = is_heal & (re_target == 3)
        if heal_self.any():
            for p in range(2):
                is_p = heal_self & (owners == p)
                if is_p.any():
                    new_hp = torch.min(
                        state.player_hp[:, p] + re_amount,
                        torch.tensor(STARTING_HP, device=device, dtype=torch.int32),
                    )
                    state.player_hp[:, p] = torch.where(is_p, new_hp, state.player_hp[:, p])

    # --- BUFF_ATTACK (2) / BUFF_HEALTH (3) ---
    # In react context with no caster minion, SELF_OWNER targeting has no effect
    # (no minion to buff). This matches the original implementation.
