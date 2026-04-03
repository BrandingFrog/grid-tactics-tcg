"""Batched react stack operations and LIFO resolution.

The react stack resolves in fixed-iteration loops with masking.
NEGATE effects cancel the next entry in LIFO order.
"""

from __future__ import annotations

import torch

from grid_tactics.tensor_engine.constants import (
    EMPTY,
    GRID_COLS,
    MAX_MINIONS,
    MAX_REACT_DEPTH,
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
        safe_cid = entry_cid.clamp(min=0)

        # Check card type
        ct = card_table.card_type[safe_cid]           # [N]
        is_react_card = (ct == 2)                       # CardType.REACT
        is_multi = card_table.is_multi_purpose[safe_cid]  # [N]

        # --- REACT cards ---
        react_resolve = should_resolve & is_react_card
        if react_resolve.any():
            # Check for NEGATE effects
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
            caster_owners = entry_player
            # React cards have no caster minion on board
            caster_slots = torch.full((N,), -1, dtype=torch.int32, device=device)

            apply_effects_batch(
                state, safe_cid, 0, caster_owners, caster_slots, tgt_flat,
                card_table, react_resolve,
            )

        # --- Multi-purpose cards ---
        multi_resolve = should_resolve & is_multi & ~is_react_card
        if multi_resolve.any():
            re_type = card_table.react_effect_type[safe_cid]     # [N]
            re_target = card_table.react_effect_target[safe_cid]  # [N]
            re_amount = card_table.react_effect_amount[safe_cid]  # [N]

            # DEPLOY_SELF (5)
            deploy_mask = multi_resolve & (re_type == 5)
            if deploy_mask.any():
                for i in range(N):
                    if not deploy_mask[i]:
                        continue
                    tf = entry_target[i].item()
                    if tf < 0 or tf >= 25:
                        continue
                    row = tf // GRID_COLS
                    col = tf % GRID_COLS
                    cid = entry_cid[i].item()
                    owner = entry_player[i].item()
                    slot = state.next_minion_slot[i].item()
                    if slot >= MAX_MINIONS:
                        continue
                    state.board[i, row, col] = slot
                    state.minion_card_id[i, slot] = cid
                    state.minion_owner[i, slot] = owner
                    state.minion_row[i, slot] = row
                    state.minion_col[i, slot] = col
                    state.minion_health[i, slot] = card_table.health[cid].item()
                    state.minion_atk_bonus[i, slot] = 0
                    state.minion_alive[i, slot] = True
                    state.next_minion_slot[i] += 1

            # Other react effects (non-DEPLOY_SELF)
            other_multi = multi_resolve & (re_type != 5) & (re_type >= 0)
            if other_multi.any():
                tgt_flat = torch.where(entry_target < 25, entry_target, torch.tensor(-1, device=device))
                caster_owners = entry_player
                caster_slots = torch.full((N,), -1, dtype=torch.int32, device=device)

                # Build per-effect tensors for the react_effect
                # We create temporary "virtual" effect data for apply_effects_batch
                # by directly applying the react_effect
                for i in range(N):
                    if not other_multi[i]:
                        continue
                    _apply_single_react_effect(
                        state, i,
                        re_type[i].item(), re_target[i].item(),
                        re_amount[i].item(), entry_player[i].item(),
                        tgt_flat[i].item(), card_table,
                    )


def _apply_single_react_effect(state, game_idx, etype, etarget, eamount, owner, target_flat, card_table):
    """Apply a single react effect for one game."""
    N = state.board.shape[0]
    device = state.board.device

    if etype == 0:  # DAMAGE
        if etarget == 0:  # SINGLE_TARGET
            if 0 <= target_flat < 25:
                row, col = target_flat // GRID_COLS, target_flat % GRID_COLS
                slot = state.board[game_idx, row, col].item()
                if slot >= 0:
                    state.minion_health[game_idx, slot] -= eamount
        elif etarget == 1:  # ALL_ENEMIES
            for s in range(MAX_MINIONS):
                if state.minion_alive[game_idx, s] and state.minion_owner[game_idx, s].item() != owner:
                    state.minion_health[game_idx, s] -= eamount
        elif etarget == 3:  # SELF_OWNER
            state.player_hp[game_idx, owner] -= eamount

    elif etype == 1:  # HEAL
        if etarget == 0:  # SINGLE_TARGET
            if 0 <= target_flat < 25:
                row, col = target_flat // GRID_COLS, target_flat % GRID_COLS
                slot = state.board[game_idx, row, col].item()
                if slot >= 0:
                    cid = state.minion_card_id[game_idx, slot].item()
                    base_hp = card_table.health[cid].item()
                    state.minion_health[game_idx, slot] = min(
                        state.minion_health[game_idx, slot].item() + eamount, base_hp
                    )
        elif etarget == 3:  # SELF_OWNER
            from grid_tactics.tensor_engine.constants import STARTING_HP
            new_hp = min(state.player_hp[game_idx, owner].item() + eamount, STARTING_HP)
            state.player_hp[game_idx, owner] = new_hp

    elif etype == 2:  # BUFF_ATTACK
        if etarget == 3:  # SELF_OWNER -- no caster minion for react
            pass  # No minion to buff in react context

    elif etype == 3:  # BUFF_HEALTH
        if etarget == 3:
            pass  # No minion to buff
