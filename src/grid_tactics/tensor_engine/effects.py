"""Batched effect resolution via CardTable lookup.

All effects are resolved as tensor operations over the batch dimension.
The loop over MAX_EFFECTS_PER_CARD is a fixed 3-iteration Python loop
(not over batch), which is fine for torch.compile.
"""

from __future__ import annotations

import torch

from grid_tactics.tensor_engine.constants import (
    GRID_COLS,
    MAX_DECK,
    MAX_EFFECTS_PER_CARD,
    MAX_HAND,
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
        _apply_promote(state, active & (etype == 7), card_ids, caster_owners, card_table)
        _apply_tutor(state, active & (etype == 8), card_ids, caster_owners, card_table)
        _apply_destroy(state, active & (etype == 9), etarget, target_flat_pos)


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


def _apply_promote(state, active, card_ids, caster_owners, card_table):
    """PROMOTE: Transform a friendly minion of promote_target type into the dying card.

    Giant Rat dies -> one friendly Rat becomes a Giant Rat (3/3, same position).
    Unique constraint: only promotes if no other copy of this card is alive on board.
    Picks the most advanced friendly target (closest to enemy back row).
    """
    if not active.any():
        return
    N = active.shape[0]
    device = active.device
    arange_n = torch.arange(N, device=device)

    safe_ids = card_ids.clamp(min=0).long()
    promote_target_cid = card_table.promote_target_id[safe_ids]  # [N]
    is_unique = card_table.is_unique[safe_ids]  # [N]

    # Check unique constraint: skip if another copy of this card already alive on board
    has_existing = torch.zeros(N, dtype=torch.bool, device=device)
    for s in range(MAX_MINIONS):
        has_existing |= (
            active
            & state.minion_alive[:, s]
            & (state.minion_owner[:, s] == caster_owners)
            & (state.minion_card_id[:, s] == card_ids)
        )
    can_promote = active & (promote_target_cid >= 0) & ~(is_unique & has_existing)

    if not can_promote.any():
        return

    # Find the best candidate: friendly, alive, matching promote_target_cid
    # Pick most advanced (highest row for P0, lowest row for P1)
    best_slot = torch.full((N,), -1, dtype=torch.long, device=device)
    best_score = torch.full((N,), -1, dtype=torch.int32, device=device)

    for s in range(MAX_MINIONS):
        is_candidate = (
            can_promote
            & state.minion_alive[:, s]
            & (state.minion_owner[:, s] == caster_owners)
            & (state.minion_card_id[:, s] == promote_target_cid)
        )
        if not is_candidate.any():
            continue
        # Score: P0 wants high row (forward = toward row 4), P1 wants low row (toward row 0)
        row = state.minion_row[:, s]
        score = torch.where(caster_owners == 0, row, 4 - row)
        better = is_candidate & (score > best_score)
        best_slot = torch.where(better, torch.tensor(s, device=device, dtype=torch.long), best_slot)
        best_score = torch.where(better, score, best_score)

    # Apply promotion: transform the target minion into the dying card's type
    do_promote = can_promote & (best_slot >= 0)
    if not do_promote.any():
        return

    safe_slot = best_slot.clamp(min=0)
    new_hp = card_table.health[safe_ids]

    # Transform: change card_id (base attack comes from card_table lookup), reset HP and bonus
    state.minion_card_id[arange_n, safe_slot] = torch.where(
        do_promote, card_ids, state.minion_card_id[arange_n, safe_slot]
    )
    state.minion_health[arange_n, safe_slot] = torch.where(
        do_promote, new_hp, state.minion_health[arange_n, safe_slot]
    )
    state.minion_atk_bonus[arange_n, safe_slot] = torch.where(
        do_promote, torch.tensor(0, device=device, dtype=torch.int32),
        state.minion_atk_bonus[arange_n, safe_slot]
    )


def _apply_tutor(state, active, card_ids, caster_owners, card_table):
    """TUTOR: Search deck for tutor_target card and add to hand."""
    if not active.any():
        return
    N = active.shape[0]
    device = active.device
    arange_n = torch.arange(N, device=device)

    safe_ids = card_ids.clamp(0).long()
    target_cid = card_table.tutor_target_id[safe_ids]  # [N]
    valid = active & (target_cid >= 0)

    if not valid.any():
        return

    player_idx = caster_owners.long()
    deck_top = state.deck_tops[arange_n, player_idx]  # [N]
    deck_size = state.deck_sizes[arange_n, player_idx]  # [N]

    # Search deck for target card (loop over fixed MAX_DECK positions)
    found_pos = torch.full((N,), -1, dtype=torch.long, device=device)
    for d in range(MAX_DECK):
        d_card = state.decks[arange_n, player_idx, d]  # [N]
        in_deck = (d >= deck_top) & (d < deck_size)
        is_match = valid & in_deck & (d_card == target_cid) & (found_pos < 0)
        found_pos = torch.where(is_match, torch.tensor(d, device=device, dtype=torch.long), found_pos)

    found = valid & (found_pos >= 0)
    if not found.any():
        return

    safe_found = found_pos.clamp(0).long()
    tutored_card = state.decks[arange_n, player_idx, safe_found]

    # Remove from deck: swap with last card, shrink size
    last_idx = (deck_size - 1).clamp(0).long()
    last_card = state.decks[arange_n, player_idx, last_idx]
    state.decks[arange_n, player_idx, safe_found] = torch.where(
        found, last_card, state.decks[arange_n, player_idx, safe_found]
    )
    state.decks[arange_n, player_idx, last_idx] = torch.where(
        found, torch.tensor(-1, device=device, dtype=state.decks.dtype),
        state.decks[arange_n, player_idx, last_idx]
    )
    state.deck_sizes[arange_n, player_idx] = torch.where(
        found, deck_size - 1, state.deck_sizes[arange_n, player_idx]
    )

    # Add to hand (if hand not full)
    hand_size = state.hand_sizes[arange_n, player_idx]
    safe_hs = hand_size.clamp(0, MAX_HAND - 1).long()
    can_add = found & (hand_size < MAX_HAND)
    state.hands[arange_n, player_idx, safe_hs] = torch.where(
        can_add, tutored_card, state.hands[arange_n, player_idx, safe_hs]
    )
    state.hand_sizes[arange_n, player_idx] = torch.where(
        can_add, hand_size + 1, state.hand_sizes[arange_n, player_idx]
    )


def _apply_destroy(state, active, etarget, target_flat_pos):
    """DESTROY: Set target minion health to 0 (cleanup handles removal)."""
    if not active.any():
        return
    N = active.shape[0]
    device = active.device
    arange_n = torch.arange(N, device=device)

    # SINGLE_TARGET (0): destroy minion at target position
    single = active & (etarget == 0)
    if single.any():
        slot = _find_minion_slot_at_pos(state, target_flat_pos)
        valid = single & (slot >= 0)
        if valid.any():
            safe_slot = slot.clamp(min=0)
            state.minion_health[arange_n, safe_slot] = torch.where(
                valid, torch.tensor(0, device=device, dtype=torch.int32),
                state.minion_health[arange_n, safe_slot]
            )
